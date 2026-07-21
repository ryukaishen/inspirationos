"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import {
  ApiError,
  FINISHED_JOB_STATUSES,
  getJob,
  listAdvisorReviews,
  requestAdvisorReview,
} from "@/lib/api";

export function AdvisorPanel({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  // null = follow the latest version; a number pins an older one.
  const [pinnedVersion, setPinnedVersion] = useState<number | null>(null);

  const reviews = useQuery({
    queryKey: ["advisor", projectId],
    queryFn: () => listAdvisorReviews(projectId),
  });

  const request = useMutation({
    mutationFn: () => requestAdvisorReview(projectId),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  });

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId as number),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status !== undefined && FINISHED_JOB_STATUSES.includes(status) ? false : 1000;
    },
  });
  const jobFinished = job.data !== undefined && FINISHED_JOB_STATUSES.includes(job.data.status);
  useEffect(() => {
    // Fold the finished job's result into the version list; `running` and the
    // shown version are derived state, so nothing else needs resetting.
    if (jobFinished) {
      void queryClient.invalidateQueries({ queryKey: ["advisor", projectId] });
    }
  }, [jobFinished, projectId, queryClient]);

  const versions = reviews.data ?? [];
  const shown =
    versions.find((review) => review.version === pinnedVersion) ?? versions[0] ?? null;
  const running = jobId !== null && !jobFinished;

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4" data-testid="advisor-panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-medium">Project Advisor</p>
          <p className="text-sm text-muted-foreground">
            Honest critique: commonality, comparative strength, recruiter impact,
            prerequisites, and a week-by-week plan. Regenerating keeps every earlier version.
          </p>
        </div>
        <Button
          size="sm"
          data-testid="advisor-request"
          disabled={running}
          onClick={() => request.mutate()}
        >
          {running
            ? "Reviewing…"
            : versions.length > 0
              ? "Regenerate review"
              : "Request review"}
        </Button>
      </div>

      {request.isError && (
        <p className="text-sm text-destructive" data-testid="advisor-error">
          {request.error instanceof ApiError
            ? request.error.message
            : "Advisor request failed."}
        </p>
      )}
      {job.data?.status === "failed" && (
        <p className="text-sm text-destructive" data-testid="advisor-job-failed">
          The advisor job failed ({job.data.error ?? "unknown error"}).
        </p>
      )}

      {versions.length > 1 && (
        <div className="flex flex-wrap items-center gap-1" data-testid="advisor-versions">
          <span className="text-xs text-muted-foreground">Versions:</span>
          {versions.map((review) => (
            <Button
              key={review.id}
              size="sm"
              variant={review.version === shown?.version ? "secondary" : "ghost"}
              data-testid={`advisor-version-${review.version}`}
              onClick={() => setPinnedVersion(review.version)}
            >
              v{review.version}
            </Button>
          ))}
        </div>
      )}

      {versions.length === 0 && !running && (
        <p className="text-sm text-muted-foreground" data-testid="advisor-empty">
          No review yet.
        </p>
      )}

      {shown?.payload && (
        <div className="space-y-3 text-sm" data-testid="advisor-review">
          <div data-testid="advisor-commonality">
            <p className="font-medium">
              Commonality:{" "}
              <span className="capitalize">{shown.payload.commonality.verdict.replace(/_/g, " ")}</span>
            </p>
            <p className="text-muted-foreground">{shown.payload.commonality.reasoning}</p>
          </div>
          <div data-testid="advisor-comparative">
            <p className="font-medium">Comparative strength</p>
            <p className="text-muted-foreground">{shown.payload.comparative_strength}</p>
          </div>
          <div data-testid="advisor-recruiter">
            <p className="font-medium">Recruiter impact</p>
            <p className="text-muted-foreground">{shown.payload.recruiter_impact}</p>
          </div>
          <div data-testid="advisor-prerequisites">
            <p className="font-medium">Prerequisites</p>
            <ul className="list-inside list-disc text-muted-foreground">
              {shown.payload.prerequisites.map((prerequisite) => (
                <li key={prerequisite}>{prerequisite}</li>
              ))}
            </ul>
          </div>
          <div data-testid="advisor-week-by-week">
            <p className="font-medium">Week-by-week plan</p>
            <ul className="space-y-1 text-muted-foreground">
              {shown.payload.week_by_week.map((entry) => (
                <li key={entry.week} data-testid="advisor-week">
                  <span className="font-medium text-foreground">Week {entry.week}:</span>{" "}
                  {entry.focus} — <em>{entry.deliverable}</em>
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-muted-foreground">
            v{shown.version} · {shown.provider} · {new Date(shown.created_at).toLocaleString()}
          </p>
        </div>
      )}
    </section>
  );
}
