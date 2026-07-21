"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { CompareDialog } from "@/components/projects/compare-dialog";
import { GenerateDialog } from "@/components/projects/generate-dialog";
import { ProjectCard } from "@/components/projects/project-card";
import { WeightSliders } from "@/components/projects/weight-sliders";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  FINISHED_JOB_STATUSES,
  PROJECT_STATUSES,
  combineProjects,
  getJob,
  getSettings,
  listProjects,
  updateScoringWeights,
  type ProjectStatus,
} from "@/lib/api";
import { rankProjects, type ScoreDimension, type Weights } from "@/lib/scoring";

export default function ProjectsPage() {
  const queryClient = useQueryClient();
  const [weights, setWeights] = useState<Weights>({});
  const [weightsReady, setWeightsReady] = useState(false);
  const [statusFilter, setStatusFilter] = useState<"all" | ProjectStatus>("all");
  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);

  const projects = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  // Initialize the sliders once from the persisted weights (settings-page
  // pattern); afterwards the drafts are user-owned until saved.
  if (settings.data && !weightsReady) {
    setWeights(settings.data.scoring_weights);
    setWeightsReady(true);
  }

  const saveWeights = useMutation({
    mutationFn: () => updateScoringWeights(weights),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const combine = useMutation({
    mutationFn: (parents: [number, number]) => combineProjects(parents),
    onSuccess: (accepted) => {
      setSelectedIds([]);
      setActiveJobId(accepted.job_id);
    },
  });

  const activeJob = useQuery({
    queryKey: ["job", activeJobId],
    queryFn: () => getJob(activeJobId as number),
    enabled: activeJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 1000;
    },
  });
  const jobFinished =
    activeJob.data !== undefined && FINISHED_JOB_STATUSES.includes(activeJob.data.status);
  useEffect(() => {
    if (jobFinished) {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [jobFinished, queryClient]);

  const allDomains = useMemo(() => {
    const domains = new Set<string>();
    for (const project of projects.data?.projects ?? []) {
      for (const domain of project.domains) domains.add(domain);
    }
    return [...domains].sort();
  }, [projects.data]);

  const visible = useMemo(() => {
    const filtered = (projects.data?.projects ?? []).filter(
      (project) =>
        (statusFilter === "all" || project.status === statusFilter) &&
        (domainFilter === "all" || project.domains.includes(domainFilter)),
    );
    // Pure client-side re-rank: recomputes on every weight change with no
    // API call (the acceptance criterion for weight sliders).
    return rankProjects(filtered, weights);
  }, [projects.data, statusFilter, domainFilter, weights]);

  const selectedProjects = useMemo(
    () => (projects.data?.projects ?? []).filter((project) => selectedIds.includes(project.id)),
    [projects.data, selectedIds],
  );

  function toggleSelect(projectId: number) {
    setSelectedIds((current) =>
      current.includes(projectId)
        ? current.filter((id) => id !== projectId)
        : [...current, projectId],
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-6 py-12">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <p className="text-sm text-muted-foreground">
          AI-generated portfolio project ideas, grounded in your saved inspiration and career
          profile. Every idea cites the items it came from; scores are transparent and
          re-rankable.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button data-testid="generate-open" onClick={() => setGenerateOpen(true)}>
          Generate projects
        </Button>
        <Button
          variant="outline"
          data-testid="compare-open"
          disabled={selectedProjects.length < 2 || selectedProjects.length > 3}
          onClick={() => setCompareOpen(true)}
        >
          Compare ({selectedProjects.length})
        </Button>
        <Button
          variant="outline"
          data-testid="combine-start"
          disabled={selectedProjects.length !== 2 || combine.isPending}
          onClick={() =>
            combine.mutate([selectedProjects[0].id, selectedProjects[1].id] as [number, number])
          }
        >
          Combine two ideas
        </Button>
        {combine.isError && (
          <p className="text-sm text-destructive" data-testid="combine-error">
            {combine.error instanceof ApiError ? combine.error.message : "Combine failed."}
          </p>
        )}
      </div>

      {activeJobId !== null && activeJob.data && (
        <p className="text-sm text-muted-foreground" data-testid="generation-status">
          {activeJob.data.status === "succeeded"
            ? "Generation complete."
            : activeJob.data.status === "failed"
              ? `Generation failed (${activeJob.data.error ?? "unknown error"}).`
              : `Generating… ${activeJob.data.progress}/${activeJob.data.total}`}
        </p>
      )}

      <WeightSliders
        weights={weights}
        onWeightChange={(dimension: ScoreDimension, value: number) =>
          setWeights((current) => ({ ...current, [dimension]: value }))
        }
        onSave={() => saveWeights.mutate()}
        saving={saveWeights.isPending}
        saved={saveWeights.isSuccess}
        saveError={
          saveWeights.isError
            ? saveWeights.error instanceof ApiError
              ? saveWeights.error.message
              : "Saving failed."
            : null
        }
      />

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          Status
          <select
            aria-label="Filter by status"
            data-testid="filter-status"
            className="rounded-md border border-input bg-background px-2 py-1"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as "all" | ProjectStatus)}
          >
            <option value="all">all</option>
            {PROJECT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          Domain
          <select
            aria-label="Filter by domain"
            data-testid="filter-domain"
            className="rounded-md border border-input bg-background px-2 py-1"
            value={domainFilter}
            onChange={(event) => setDomainFilter(event.target.value)}
          >
            <option value="all">all</option>
            {allDomains.map((domain) => (
              <option key={domain} value={domain}>
                {domain}
              </option>
            ))}
          </select>
        </label>
      </div>

      {projects.isLoading && <p className="text-sm text-muted-foreground">Loading projects…</p>}
      {projects.data && visible.length === 0 && (
        <p className="text-sm text-muted-foreground" data-testid="no-projects">
          No projects yet — generate some from your clusters.
        </p>
      )}

      <section className="space-y-3" data-testid="project-list">
        {visible.map((project) => (
          <ProjectCard
            key={project.id}
            project={project}
            weights={weights}
            selected={selectedIds.includes(project.id)}
            onToggleSelect={toggleSelect}
          />
        ))}
      </section>

      <GenerateDialog
        open={generateOpen}
        onOpenChange={setGenerateOpen}
        onStarted={setActiveJobId}
      />
      <CompareDialog
        open={compareOpen}
        onOpenChange={setCompareOpen}
        projects={selectedProjects.slice(0, 3)}
        weights={weights}
      />
    </main>
  );
}
