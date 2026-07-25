"use client";

import Link from "next/link";

import { ScoreBars } from "@/components/projects/score-bars";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import type { ProjectRead } from "@/lib/api";
import { computeScore, type Weights } from "@/lib/scoring";

const STATUS_LABELS: Record<ProjectRead["status"], string> = {
  idea: "Idea",
  shortlisted: "Shortlisted",
  planned: "Planned",
  in_progress: "In progress",
  completed: "Completed",
  archived: "Archived",
};

export interface ProjectCardProps {
  project: ProjectRead;
  weights: Weights;
  selected: boolean;
  onToggleSelect: (projectId: number) => void;
}

export function ProjectCard({ project, weights, selected, onToggleSelect }: ProjectCardProps) {
  const total = computeScore(project.scores, weights);
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4" data-testid="project-card">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Checkbox
            aria-label={`Select ${project.title}`}
            data-testid="project-select"
            checked={selected}
            onChange={() => onToggleSelect(project.id)}
          />
          <div className="space-y-1">
            <p className="font-medium leading-tight">
              <Link
                className="hover:underline"
                href={`/projects/${project.id}`}
                data-testid="project-title"
              >
                {project.title}
              </Link>
            </p>
            <p className="text-sm text-muted-foreground" data-testid="project-one-liner">
              {project.one_liner}
            </p>
            <div className="flex flex-wrap items-center gap-1">
              <Badge variant="outline" data-testid="project-status">
                {STATUS_LABELS[project.status]}
              </Badge>
              {project.parent_project_ids.length > 0 && (
                <Badge variant="success" data-testid="project-combined-badge">
                  Combined
                </Badge>
              )}
              {[...new Set(project.domains)].map((domain) => (
                <Badge key={domain} variant="secondary" data-testid="project-domain">
                  {domain}
                </Badge>
              ))}
            </div>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-lg font-semibold tabular-nums" data-testid="project-score">
            {total.toFixed(1)}
          </p>
          <p className="text-xs text-muted-foreground">weighted score</p>
        </div>
      </div>
      <ScoreBars scores={project.scores} />
    </div>
  );
}
