"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdvisorPanel } from "@/components/projects/advisor-panel";
import { CareerArtifactsPanel } from "@/components/projects/career-artifacts-panel";
import { ExportPanel } from "@/components/projects/export-panel";
import { MilestoneEditor } from "@/components/projects/milestone-editor";
import { ScoreBars } from "@/components/projects/score-bars";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ApiError,
  FINISHED_JOB_STATUSES,
  PROJECT_STATUSES,
  getJob,
  getProject,
  regenerateProject,
  updateProject,
  type ProjectStatus,
} from "@/lib/api";

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

export default function ProjectDetailPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [oneLinerDraft, setOneLinerDraft] = useState("");
  const [summaryDraft, setSummaryDraft] = useState("");
  const [domainsDraft, setDomainsDraft] = useState("");
  const [stackDraft, setStackDraft] = useState("");
  const [difficultyDraft, setDifficultyDraft] = useState("");
  const [durationDraft, setDurationDraft] = useState("");
  const [regenerateJobId, setRegenerateJobId] = useState<number | null>(null);

  const detail = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
    enabled: Number.isInteger(projectId) && projectId > 0,
  });
  const project = detail.data;

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    await queryClient.invalidateQueries({ queryKey: ["projects"] });
  };

  const saveEdit = useMutation({
    mutationFn: () =>
      updateProject(projectId, {
        title: titleDraft.trim() || undefined,
        one_liner: oneLinerDraft.trim() || undefined,
        summary_md: summaryDraft.trim() || undefined,
        domains: parseList(domainsDraft),
        tech_stack: parseList(stackDraft),
        difficulty: difficultyDraft.trim() || null,
        duration_estimate: durationDraft.trim() || null,
      }),
    onSuccess: async () => {
      setEditing(false);
      await invalidate();
    },
  });

  const setStatus = useMutation({
    mutationFn: (status: ProjectStatus) => updateProject(projectId, { status }),
    onSuccess: invalidate,
  });

  const regenerate = useMutation({
    mutationFn: () => regenerateProject(projectId),
    onSuccess: (accepted) => setRegenerateJobId(accepted.job_id),
  });

  const regenerateJob = useQuery({
    queryKey: ["job", regenerateJobId],
    queryFn: () => getJob(regenerateJobId as number),
    enabled: regenerateJobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 1000;
    },
  });
  const regenerateFinished =
    regenerateJob.data !== undefined &&
    FINISHED_JOB_STATUSES.includes(regenerateJob.data.status);
  useEffect(() => {
    if (regenerateFinished) {
      void queryClient.invalidateQueries({ queryKey: ["project", projectId] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    }
  }, [regenerateFinished, projectId, queryClient]);

  function startEditing() {
    if (!project) return;
    setTitleDraft(project.title);
    setOneLinerDraft(project.one_liner);
    setSummaryDraft(project.summary_md);
    setDomainsDraft(project.domains.join(", "));
    setStackDraft(project.tech_stack.join(", "));
    setDifficultyDraft(project.difficulty ?? "");
    setDurationDraft(project.duration_estimate ?? "");
    setEditing(true);
  }

  const regenerating =
    regenerate.isPending || (regenerateJobId !== null && !regenerateFinished);

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-6 py-12">
      <div>
        <p className="text-sm text-muted-foreground">
          <Link className="underline" href="/projects">
            ← Back to projects
          </Link>
        </p>
        {detail.isError && <p className="text-destructive">Project not found.</p>}
      </div>

      {project && (
        <>
          <div className="space-y-3 rounded-lg border bg-card p-4" data-testid="project-detail">
            <div className="flex items-start justify-between gap-3">
              <div className="space-y-1">
                <h1
                  className="text-xl font-semibold tracking-tight"
                  data-testid="project-detail-title"
                >
                  {project.title}
                </h1>
                <p className="text-sm text-muted-foreground">{project.one_liner}</p>
                <div className="flex flex-wrap items-center gap-1">
                  {project.parent_project_ids.length > 0 && (
                    <Badge variant="success" data-testid="detail-combined-badge">
                      Combined from #{project.parent_project_ids.join(" + #")}
                    </Badge>
                  )}
                  {project.domains.map((domain) => (
                    <Badge key={domain} variant="secondary">
                      {domain}
                    </Badge>
                  ))}
                  {project.difficulty && <Badge variant="outline">{project.difficulty}</Badge>}
                  {project.duration_estimate && (
                    <Badge variant="outline">{project.duration_estimate}</Badge>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <select
                  aria-label="Project status"
                  data-testid="detail-status-select"
                  className="rounded-md border border-input bg-background px-2 py-1 text-sm"
                  value={project.status}
                  onChange={(event) => setStatus.mutate(event.target.value as ProjectStatus)}
                >
                  {PROJECT_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="detail-edit"
                  onClick={() => (editing ? setEditing(false) : startEditing())}
                >
                  {editing ? "Cancel" : "Edit"}
                </Button>
              </div>
            </div>

            {!editing && (
              <div
                className="whitespace-pre-wrap text-sm text-muted-foreground"
                data-testid="project-summary"
              >
                {project.summary_md}
              </div>
            )}

            {editing && (
              <div className="space-y-2" data-testid="detail-edit-form">
                <Input
                  aria-label="Title"
                  data-testid="detail-title-input"
                  value={titleDraft}
                  onChange={(event) => setTitleDraft(event.target.value)}
                />
                <Input
                  aria-label="One-liner"
                  data-testid="detail-one-liner-input"
                  value={oneLinerDraft}
                  onChange={(event) => setOneLinerDraft(event.target.value)}
                />
                <Textarea
                  aria-label="Summary"
                  data-testid="detail-summary-input"
                  rows={6}
                  value={summaryDraft}
                  onChange={(event) => setSummaryDraft(event.target.value)}
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="block text-xs">
                    Domains (comma-separated)
                    <Input
                      className="mt-1"
                      value={domainsDraft}
                      onChange={(event) => setDomainsDraft(event.target.value)}
                    />
                  </label>
                  <label className="block text-xs">
                    Tech stack (comma-separated)
                    <Input
                      className="mt-1"
                      value={stackDraft}
                      onChange={(event) => setStackDraft(event.target.value)}
                    />
                  </label>
                  <label className="block text-xs">
                    Difficulty
                    <Input
                      className="mt-1"
                      value={difficultyDraft}
                      onChange={(event) => setDifficultyDraft(event.target.value)}
                    />
                  </label>
                  <label className="block text-xs">
                    Duration estimate
                    <Input
                      className="mt-1"
                      value={durationDraft}
                      onChange={(event) => setDurationDraft(event.target.value)}
                    />
                  </label>
                </div>
                <Button
                  size="sm"
                  data-testid="detail-save"
                  disabled={saveEdit.isPending}
                  onClick={() => saveEdit.mutate()}
                >
                  Save
                </Button>
                {saveEdit.isError && (
                  <p className="text-xs text-destructive">
                    {saveEdit.error instanceof ApiError
                      ? saveEdit.error.message
                      : "Saving failed."}
                  </p>
                )}
              </div>
            )}

            {(project.datasets.length > 0 ||
              project.tech_stack.length > 0 ||
              project.skills_demonstrated.length > 0 ||
              project.risks.length > 0) && (
              <div className="grid gap-3 text-sm sm:grid-cols-2">
                {project.tech_stack.length > 0 && (
                  <div>
                    <p className="font-medium">Tech stack</p>
                    <p className="text-muted-foreground">{project.tech_stack.join(", ")}</p>
                  </div>
                )}
                {project.skills_demonstrated.length > 0 && (
                  <div>
                    <p className="font-medium">Skills demonstrated</p>
                    <p className="text-muted-foreground">
                      {project.skills_demonstrated.join(", ")}
                    </p>
                  </div>
                )}
                {project.datasets.length > 0 && (
                  <div>
                    <p className="font-medium">Datasets</p>
                    <p className="text-muted-foreground">{project.datasets.join(", ")}</p>
                  </div>
                )}
                {project.risks.length > 0 && (
                  <div>
                    <p className="font-medium">Risks</p>
                    <p className="text-muted-foreground">{project.risks.join("; ")}</p>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3 border-t pt-3">
              <p className="text-xs text-muted-foreground" data-testid="project-sources">
                Grounded in {project.source.item_ids?.length ?? 0} item(s)
                {(project.source.cluster_ids?.length ?? 0) > 0 &&
                  ` across ${project.source.cluster_ids?.length} cluster(s)`}{" "}
                · {project.source.provider} / {project.source.model}
              </p>
              <Button
                size="sm"
                variant="outline"
                data-testid="detail-regenerate"
                disabled={regenerating}
                onClick={() => regenerate.mutate()}
              >
                {regenerating ? "Regenerating…" : "Regenerate"}
              </Button>
              {regenerateJob.data?.status === "failed" && (
                <p className="text-xs text-destructive" data-testid="regenerate-failed">
                  Regeneration failed ({regenerateJob.data.error ?? "unknown error"}).
                </p>
              )}
            </div>
          </div>

          <section className="space-y-3 rounded-lg border bg-card p-4">
            <p className="font-medium">Scores</p>
            <ScoreBars scores={project.scores} />
          </section>

          <MilestoneEditor projectId={projectId} milestones={project.milestones} />
          <AdvisorPanel projectId={projectId} />
          <CareerArtifactsPanel projectId={projectId} />
          <ExportPanel projectId={projectId} />
        </>
      )}
    </main>
  );
}
