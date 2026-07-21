"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ProjectRead } from "@/lib/api";
import { computeScore, DIMENSION_LABELS, SCORE_DIMENSIONS, type Weights } from "@/lib/scoring";

export interface CompareDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projects: ProjectRead[]; // 2-3 selected projects
  weights: Weights;
}

/** Side-by-side comparison: one aligned row per scoring dimension. */
export function CompareDialog({ open, onOpenChange, projects, weights }: CompareDialogProps) {
  const columns = `minmax(7rem, 1fr) repeat(${projects.length}, minmax(0, 2fr))`;
  return (
    <Dialog open={open} onOpenChange={onOpenChange} className="max-w-3xl">
      <DialogHeader>
        <DialogTitle>Compare projects</DialogTitle>
      </DialogHeader>
      <div className="grid gap-x-4 gap-y-3 text-sm" style={{ gridTemplateColumns: columns }} data-testid="compare-grid">
        <span aria-hidden />
        {projects.map((project) => (
          <div key={project.id} className="space-y-0.5" data-testid="compare-header">
            <p className="font-medium leading-tight">{project.title}</p>
            <p className="text-xs text-muted-foreground">
              weighted {computeScore(project.scores, weights).toFixed(1)}
            </p>
          </div>
        ))}
        {SCORE_DIMENSIONS.map((dimension) => (
          <div key={dimension} className="contents" data-testid={`compare-row-${dimension}`}>
            <span className="text-xs text-muted-foreground">{DIMENSION_LABELS[dimension]}</span>
            {projects.map((project) => {
              const entry = project.scores[dimension];
              return (
                <div key={project.id} className="space-y-0.5" data-testid="compare-cell">
                  {entry ? (
                    <>
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{
                              width: `${Math.min(100, Math.max(0, (entry.score / 10) * 100))}%`,
                            }}
                          />
                        </div>
                        <span className="text-xs font-medium tabular-nums">
                          {entry.score.toFixed(1)}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground">{entry.rationale}</p>
                    </>
                  ) : (
                    <span className="text-xs text-muted-foreground">—</span>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>
          Close
        </Button>
      </DialogFooter>
    </Dialog>
  );
}
