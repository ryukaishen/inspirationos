"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  ApiError,
  CAREER_ARTIFACT_KINDS,
  CAREER_ARTIFACT_LABELS,
  listCareerArtifacts,
  requestCareerArtifact,
  type CareerArtifactKind,
} from "@/lib/api";
import { useJobPolling } from "@/lib/use-job-polling";

export function CareerArtifactsPanel({ projectId }: { projectId: number }) {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<CareerArtifactKind>("readme");
  const [jobId, setJobId] = useState<number | null>(null);
  // null = follow the latest version; a number pins an older one.
  const [pinnedVersion, setPinnedVersion] = useState<number | null>(null);

  const versions = useQuery({
    queryKey: ["career-artifact", projectId, kind],
    queryFn: () => listCareerArtifacts(projectId, kind),
  });

  const request = useMutation({
    mutationFn: () => requestCareerArtifact(projectId, kind),
    onSuccess: (accepted) => setJobId(accepted.job_id),
  });

  const { job, running, failed } = useJobPolling(jobId, () => {
    void queryClient.invalidateQueries({ queryKey: ["career-artifact", projectId, kind] });
    void queryClient.invalidateQueries({ queryKey: ["career-artifacts-summary", projectId] });
  });

  function selectKind(next: CareerArtifactKind) {
    setKind(next);
    setJobId(null);
    setPinnedVersion(null);
  }

  const items = versions.data ?? [];
  const shown = items.find((artifact) => artifact.version === pinnedVersion) ?? items[0] ?? null;

  return (
    <section
      className="space-y-3 rounded-lg border bg-card p-4"
      data-testid="career-artifacts-panel"
    >
      <div>
        <p className="font-medium">Career artifacts</p>
        <p className="text-sm text-muted-foreground">
          README plan, resume bullets, portfolio description, interview answer, and likely
          technical questions — generated from this project, versioned, regenerable.
        </p>
      </div>

      <div className="flex flex-wrap gap-1" data-testid="career-artifact-kind-tabs">
        {CAREER_ARTIFACT_KINDS.map((candidate) => (
          <Button
            key={candidate}
            size="sm"
            variant={candidate === kind ? "secondary" : "ghost"}
            data-testid={`career-artifact-tab-${candidate}`}
            onClick={() => selectKind(candidate)}
          >
            {CAREER_ARTIFACT_LABELS[candidate]}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button
          size="sm"
          data-testid="career-artifact-request"
          disabled={running}
          onClick={() => request.mutate()}
        >
          {running ? "Generating…" : items.length > 0 ? "Regenerate" : "Generate"}
        </Button>
        {items.length > 1 && (
          <div
            className="flex flex-wrap items-center gap-1"
            data-testid="career-artifact-versions"
          >
            <span className="text-xs text-muted-foreground">Versions:</span>
            {items.map((artifact) => (
              <Button
                key={artifact.id}
                size="sm"
                variant={artifact.version === shown?.version ? "secondary" : "ghost"}
                data-testid={`career-artifact-version-${artifact.version}`}
                onClick={() => setPinnedVersion(artifact.version)}
              >
                v{artifact.version}
              </Button>
            ))}
          </div>
        )}
      </div>

      {request.isError && (
        <p className="text-sm text-destructive" data-testid="career-artifact-error">
          {request.error instanceof ApiError ? request.error.message : "Artifact request failed."}
        </p>
      )}
      {failed && (
        <p className="text-sm text-destructive" data-testid="career-artifact-job-failed">
          Generation failed ({job?.error ?? "unknown error"}).
        </p>
      )}

      {items.length === 0 && !running && (
        <p className="text-sm text-muted-foreground" data-testid="career-artifact-empty">
          Not generated yet.
        </p>
      )}

      {shown && (
        <div className="space-y-2" data-testid="career-artifact-content">
          {shown.claims_flags.length > 0 && (
            <div
              className="flex items-start gap-2 text-xs"
              data-testid="career-artifact-claims-warning"
            >
              <Badge variant="destructive">Flagged</Badge>
              <span className="text-muted-foreground">
                Possible unverified performance claims — review before using:{" "}
                {shown.claims_flags.join("; ")}
              </span>
            </div>
          )}
          <div className="whitespace-pre-wrap text-sm text-muted-foreground">
            {shown.content_md}
          </div>
          <p className="text-xs text-muted-foreground">
            v{shown.version} · {shown.provider} · {new Date(shown.created_at).toLocaleString()}
          </p>
        </div>
      )}
    </section>
  );
}
